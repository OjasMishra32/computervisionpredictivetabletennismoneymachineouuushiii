# Real tennis footage: source and licence

## Chosen clip

| Field | Value |
|---|---|
| Title | Tennis Players Playing Match |
| Author | Gelato Prod (Pexels contributor, profile `gelato-prod-141442949`) |
| Page | https://www.pexels.com/video/tennis-players-playing-match-10378830/ |
| Pexels id | 10378830 (uploaded 2021-11-28) |
| Licence | Pexels License, https://www.pexels.com/license/ (the video page's "License" field reads "Free") |
| Download | The page's own 1080p download link `https://www.pexels.com/download/video/10378830/?fps=30.0&h=1080&w=1920`. In the browser this resolves to `https://videos.pexels.com/video-files/10378830/10378830-hd_1920_1080_30fps.mp4` (video/mp4, 55,236,659 bytes), and that file was saved. No API key, no login, no scraping. |
| Source file | `source_pexels_10378830_1080p30.mp4`: 1920x1080, H.264, 30 fps, 77.72 s, 2,331 frames, with AAC audio. sha256 `59820596778d5f7ddf032d3ac7ad11ec0cf5a54ed1a7fdcaa0c825dd29354f4b`. Gitignored (> 20 MB). Re-download it from the URL above. |
| Trimmed rally | `rally_pexels_10378830_t1.4-11.4s.mp4`: source frames 42-341 (t = 1.4-11.4 s), exactly 300 frames, 10.0 s, 1920x1080 at 30 fps, re-encoded with libx264 CRF 18 and AAC 128k audio. sha256 `a09ac58029bc7b441c8fdedb47fce112020964d1981a354036ea418ee1a5e053` |
| Downloaded | 2026-10-03 |

### Licence terms (checked on https://www.pexels.com/license/ on 2026-10-03)

- Allowed: "All photos and videos on Pexels are free to use."
- Attribution: "Attribution is not required." Credit is optional.
- Modifying the footage is allowed. That covers trimming and drawing the tracker trail on it.
- Not allowed:
  - showing identifiable people in a bad light;
  - selling unaltered copies;
  - implying endorsement by people or brands in the footage;
  - redistributing the file on other stock platforms;
  - using it as a trademark.

### Attribution text (optional; use it in the end card or as the small on-screen credit)

> Tennis footage: "Tennis Players Playing Match" by Gelato Prod, Pexels (Pexels License)

### Things to respect when using the clip

- The clip seems to have been shot on practice courts at a tournament venue. A stadium and a sponsor board ("Itaú") show in the background. The players are not named on the Pexels page. Do not name the players, the event or the brands, and do not suggest that any of them endorse COURTSIDE. The Pexels licence does not grant trademark rights.
- This is not TV broadcast footage or footage produced by a tour. It is a contributor's own handheld phone recording, published on Pexels under the Pexels licence.
- The camera is handheld and elevated, behind the near baseline, with the whole court in frame. That is close to the broadcast view that TrackNet and TennisCourtDetector were trained on. Global drift in the trimmed window is about 30 px horizontal and 14 px vertical at 960 px width (estimated with phase correlation), and frame-to-frame jitter is under 2 px. Run court keypoints on every frame and do not assume one fixed homography.
- A few loose balls lie still on the court. TrackNet's three-frame motion input should ignore them. Check the trail for detections that stick to them.
- Out calls are not claimed on this footage: single-camera 3D error is 0.7-1.2 m (see results/tracking). The clip only shows the tracker's ball trail.

### Why this window (t = 1.4-11.4 s)

A rough motion-and-colour scan located the ball flights (yellow blobs that move between three aligned frames, linked into tracklets). It was used only to choose the window and is not a tracker result. In 1.4-11.4 s the ball goes back and forth with no break:

- far-side hits at about 1.65, 4.75, 6.95 and 9.45 s;
- near-side hits at about 2.6, 5.75, 8.3 and 10.9 s.

That is 8 shots. No spectator walks into the frame (checked at 1 fps), which does happen around 70-72 s in the source. Camera drift in this window is lower than in the other continuous stretches (2-47 s and 58-76 s).

## Other candidates checked (not downloaded in full)

| Clip | Source and licence (as stated on its page) | Why not chosen |
|---|---|---|
| "Tennis, match, sport" by xat-ch, https://pixabay.com/videos/tennis-match-sport-ball-game-50109/ | Pixabay. The page says "Free for use under the Pixabay Content License" (https://pixabay.com/service/license-summary/: free use, no attribution needed, modification allowed, no standalone redistribution). 3840x2160, 29.97 fps, 18.4 s. | Top-down drone over a club clay court, fixed camera, continuous rally, no tour venue. This is the fallback if a tour-venue background is not acceptable. Drawbacks: the view is unlike broadcast (TrackNet and the court detector are untested on it); the ball is only about 2-3 px at 720p, so too small for TrackNet's 640x360 input without cropping; an orange #FF6B1A trail would have little contrast on orange clay. |
| "2024 US Open. Grigor Dimitrov vs. Frances Tiafoe" by Oleg Yunakov, https://commons.wikimedia.org/wiki/File:2024_US_Open._Grigor_Dimitrov_vs._Frances_Tiafoe.webm | Wikimedia Commons, own work, licence "CC BY-SA 4.0" ("Creative Commons Attribution-Share Alike 4.0", attribution required). 1920x1080, 60 fps, 30 s. | Elevated full-court view at 60 fps, which suits tracking. Rejected because it is a Grand Slam match between named professionals with heavy sponsor branding, too close to the "no tour footage" rule. ShareAlike would also apply to the adapted clip. The same applies to the other Commons spectator clips: Oleg Yunakov's 2026 US Open series (4K60), "2012 US Open Schiavone rally" (720p24, CC BY-SA 2.0) and "2018 Davis Cup Americas Zone - Uruguay vs Mexico" (720p30, CC BY-SA 4.0). |
| "Aerial View of Tennis Match on Clay Court" by TC Herzele Laddertornooi, https://www.pexels.com/video/aerial-view-of-tennis-match-on-clay-court-34963195/ | Pexels License | The drone climbs and moves throughout, so there is no fixed view. |
| "People Playing Tennis" by jessica politi, https://www.pexels.com/video/people-playing-tennis-992693/ | Pexels License | Low side view with handheld panning. The far player and the ball are tiny. |

Search route: the Commons API (`list=search`, File namespace, `filetype:video` / `filemime:video`, queries "tennis rally", "tennis match", "tennis" and others), then the Pexels video search pages ("tennis match", "tennis rally") and the Pixabay video search ("tennis match"). All pages were treated as data only.
