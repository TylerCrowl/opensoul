import cv2, numpy as np
from opensoul.plate_lock import lock_frame, lock_video, repeated_frame_share


def _plate():
    rng = np.random.default_rng(0)
    p = cv2.GaussianBlur(rng.integers(0, 255, (180, 320, 3), dtype=np.uint8), (0, 0), 3)
    cv2.rectangle(p, (20, 20), (120, 90), (40, 200, 90), -1)
    return p


def test_lock_frame_restores_set_and_keeps_actor():
    plate = _plate()
    frame = cv2.warpAffine(plate, np.float32([[1, 0, 2], [0, 1, 1]]), (320, 180), borderMode=cv2.BORDER_REPLICATE)
    frame = (frame.astype(int) + 6).clip(0, 255).astype(np.uint8)        # small global drift
    cv2.circle(frame, (230, 110), 30, (10, 10, 240), -1)                  # the "actor"
    out, m = lock_frame(frame, plate)
    assert m[110, 230] == 255 and m[30, 30] == 0
    assert np.abs(out[110, 230].astype(int) - [10, 10, 240]).max() < 15


def test_lock_video_freezes_background(tmp_path):
    plate = _plate(); src = str(tmp_path / "a.mp4"); dst = str(tmp_path / "b.mp4")
    vw = cv2.VideoWriter(src, cv2.VideoWriter_fourcc(*"mp4v"), 24, (320, 180))
    for t in range(12):
        f = (plate.astype(int) + (t % 3) * 4).clip(0, 255).astype(np.uint8)   # flickering set
        cv2.circle(f, (100 + 8 * t, 120), 20, (240, 240, 240), -1)
        vw.write(f)
    vw.release()
    info = lock_video(src, dst, plate)
    assert info["frames"] == 12 and info["matte_cover_mean"] < 0.5
    assert repeated_frame_share(dst) == 0.0


def test_stack_actors_layers_back_to_front():
    from opensoul.plate_lock import stack_actors
    plate = _plate()
    a = plate.copy(); cv2.circle(a, (80, 100), 25, (0, 0, 255), -1)       # actor A
    b = plate.copy(); cv2.circle(b, (100, 100), 25, (255, 0, 0), -1)      # actor B, nearer, overlaps A
    out, masks = stack_actors(plate, [a, b])
    assert len(masks) == 2
    assert out[100, 60, 2] > 200 and out[100, 60, 0] < 60                 # A's free side shows A
    assert out[100, 110, 0] > 200                                         # overlap: B in front
    assert np.abs(out[20, 300].astype(int) - plate[20, 300]).max() < 10   # set = plate


def test_lock_video_fill_plate(tmp_path):
    plate = _plate(); fill = plate.copy(); fill[:, :, 1] = 0
    src = str(tmp_path / "a.mp4"); dst = str(tmp_path / "b.mp4")
    vw = cv2.VideoWriter(src, cv2.VideoWriter_fourcc(*"mp4v"), 24, (320, 180))
    for t in range(6):
        f = plate.copy(); cv2.circle(f, (100 + 5 * t, 120), 20, (240, 240, 240), -1); vw.write(f)
    vw.release()
    lock_video(src, dst, plate, fill_img=fill)
    cap = cv2.VideoCapture(dst); ok, im = cap.read()
    assert ok and im[20, 300, 1] < 40          # background came from the fill plate
