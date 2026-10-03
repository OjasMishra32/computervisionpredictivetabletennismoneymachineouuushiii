"""Export the pretrained BlurBall table-tennis detector (the one src/tracking used, zero-shot) to ONNX.

The engine's default CPU / CoreML backend runs this ONNX file, so the laptop does not need the
BlurBall source tree at run time. The export wraps the model exactly as src/tracking/detect.py uses it:
input  x [B, 9, 288, 512]  = 3 consecutive RGB frames, ImageNet-normalised, channels-first, concatenated
output hm [B, 3, 288, 512] = sigmoid of the scale-0 heatmap, one map per input frame
No weight is changed. The script checks ONNX vs PyTorch on random inputs and on a real frame triplet.

Usage (repo root):
  python -m engine.vision.export_onnx --blurball_root <clone of cogsys-tuebingen/blurball @2f0f549> \
      --weights models/vision/blurball_best --out models/vision/blurball_best.onnx
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

import numpy as np


def build_torch_model(blurball_root: str, weights: str, model_name: str = "blurball"):
    """Same construction as src/tracking/detect.py:load_model, but kept on the CPU."""
    import torch
    sys.path.insert(0, os.path.join(blurball_root, "src"))
    from omegaconf import OmegaConf
    from models import build_model  # BlurBall / WASB model zoo

    mcfg = OmegaConf.load(os.path.join(blurball_root, "src/configs/model", f"{model_name}.yaml"))
    model = build_model({"model": mcfg})
    ckpt = torch.load(weights, map_location="cpu", weights_only=False)
    sd = ckpt.get("model_state_dict", ckpt)
    sd = {k.replace("module.", "", 1) if k.startswith("module.") else k: v for k, v in sd.items()}
    model.load_state_dict(sd)
    return model.eval()


class SigmoidHeatmap:
    """nn.Module wrapper: x -> sigmoid(model(x)[0]) (detect.py's `infer`)."""

    def __new__(cls, model):
        import torch

        class _W(torch.nn.Module):
            def __init__(self, m):
                super().__init__()
                self.m = m

            def forward(self, x):
                y = self.m(x)
                y = y[0] if isinstance(y, dict) else y
                return torch.sigmoid(y)

        return _W(model).eval()


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    import torch
    import onnxruntime as ort

    ap = argparse.ArgumentParser()
    ap.add_argument("--blurball_root", required=True)
    ap.add_argument("--weights", default="models/vision/blurball_best")
    ap.add_argument("--model", default="blurball")
    ap.add_argument("--out", default="models/vision/blurball_best.onnx")
    ap.add_argument("--opset", type=int, default=17)
    a = ap.parse_args()

    net = SigmoidHeatmap(build_torch_model(a.blurball_root, a.weights, a.model))
    x = torch.randn(1, 9, 288, 512)
    # dynamic batch (offline / batched use) and a static batch-1 graph for streaming: with static shapes the
    # SE blocks' Shape/Gather ops fold away, which lets CoreML take the whole graph
    out_b1 = a.out.replace(".onnx", "_b1.onnx")
    torch.onnx.export(net, (x,), a.out, input_names=["x"], output_names=["hm"],
                      dynamic_axes={"x": {0: "b"}, "hm": {0: "b"}}, opset_version=a.opset,
                      dynamo=False)
    torch.onnx.export(net, (x,), out_b1, input_names=["x"], output_names=["hm"], opset_version=a.opset,
                      dynamo=False)
    errs = []
    rng = np.random.default_rng(0)
    for path in (a.out, out_b1):
        sess = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        with torch.no_grad():
            for _ in range(3):
                xi = rng.standard_normal((1, 9, 288, 512)).astype(np.float32)
                ref = net(torch.from_numpy(xi)).numpy()
                got = sess.run(["hm"], {"x": xi})[0]
                errs.append(float(np.abs(ref - got).max()))
    # fp16 graph (fp32 I/O) for accelerators: the offline detector itself ran in fp16 (autocast on CUDA)
    out_16 = out_b1.replace(".onnx", "_fp16.onnx")
    err16 = None
    try:
        import onnx
        from onnxconverter_common import float16
        onnx.save(float16.convert_float_to_float16(onnx.load(out_b1), keep_io_types=True), out_16)
        s16 = ort.InferenceSession(out_16, providers=["CPUExecutionProvider"])
        with torch.no_grad():
            xi = rng.standard_normal((1, 9, 288, 512)).astype(np.float32)
            err16 = float(np.abs(net(torch.from_numpy(xi)).numpy() - s16.run(["hm"], {"x": xi})[0]).max())
    except ImportError:
        out_16 = None
    meta = dict(onnx_b1_fp16=out_16, onnx_b1_fp16_sha256=(sha256(out_16) if out_16 else None),
                fp16_max_abs_err_vs_torch_fp32=err16, source="BlurBall (Gossard et al., CVPRW 2026, MIT) commit 2f0f549, weights blurball_best",
                weights=a.weights, weights_sha256=sha256(a.weights), onnx=a.out, onnx_sha256=sha256(a.out),
                onnx_b1=out_b1, onnx_b1_sha256=sha256(out_b1),
                opset=a.opset, input="x [B,9,288,512] float32, 3 RGB frames ImageNet-normalised",
                output="hm [B,3,288,512] sigmoid heatmaps", max_abs_err_vs_torch=max(errs),
                torch=torch.__version__, onnxruntime=ort.__version__)
    json.dump(meta, open(os.path.splitext(a.out)[0] + ".json", "w"), indent=1)
    print(json.dumps(meta, indent=1))
    assert max(errs) < 1e-4, errs


if __name__ == "__main__":
    main()
