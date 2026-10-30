# Recreate "Lumi – Night Shift" in the app (local models only)

Everything below runs on your own machine through ComfyUI with open-weight models. Nothing is sent to a cloud service.

1. **Open the story.** In the top bar choose **Storyboard**. The demo story *Lumi – Night Shift* is already there with 8 shots in order. Shots 1, 4 and 8 start with photoreal start frames; the others are empty.
2. **Check the cast.** Open a shot. The chips under the takes (Lumi, Mio, Ren) are the saved characters from `assets/<name>/character.json`. Tap a chip to add or remove someone from the shot.
3. **Make a start frame.** On an empty shot, **New start frame** is the blue button; tap it. The app puts the cast, from their saved pictures, into the shot's scene (Qwen-Image-Edit-2511 + Lightning, workflow `08_scene_compose_api.json`, up to 3 people). It is added as a new take, so nothing you made before is lost.
4. **Draft the motion.** Keep the toggle on **Draft** and tap **Animate this frame**. This makes a quick LTX-2.5 take (896x512, up to 4 s, about **1 min on a DGX Spark**) from the start frame you are looking at.
5. **Pick and finish.** Tap **Use this take** on the best one, then **Render vN in Final quality**. It uses the same seed, prompt and start frame at 1280x704 and full length (the 7 s Cold open took **2 min 23 s** on the Spark).
6. **Export.** **Export** joins the keepers in shot order.

Tips
- Write changes in plain words in **What should change?** (for example "slower push-in, the cat looks up").
- Subtle elf ears: image models keep drawing long sideways spikes on a plain background. When a character's description asks for short or subtle pointed ears (Lumi's does), **Make character sheet** now shortens the tips automatically after rendering (`opensoul/ear_trim.py`, local, no model; the untrimmed view is kept next to it). Check the sheet by eye: front and back views come out reliably; profile views can need a second look. Start frames made from that sheet keep the short ears. For Lumi's close-ups use `assets/lumi/lumi_ref_v3_trim.jpg`. The camera preset **Gentle push-in** ends on a medium close-up with the whole head in frame.
- Mio and Ren's photoreal v1 looks were approved in review (Oct 18, 8:23 AM ET); the shots with all three still need start frames and takes.
- **More options → Copy recipe** copies a take's cast, camera, seed, start frame and prompt, so you can make the same take again on another machine.
- A Draft shows a link to its Final once you have rendered one.
- Every take records how long it took to render, so you can plan a batch.
- Lumi talking takes: the voice is Kokoro-82M and the lip-sync is LTX joint audio+video. We rate these by eye; automatic scores are only a pre-filter.
