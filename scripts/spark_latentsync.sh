# usage: ls_run.sh name audio [gscale]
cd ~/OpenSoul/LatentSync; source ../latentsync-env/bin/activate
python -m scripts.inference --unet_config_path configs/unet/stage2_512.yaml --inference_ckpt_path checkpoints/latentsync_unet.pt --inference_steps ${4:-20} --guidance_scale ${3:-1.5} --enable_deepcache --video_path ../rb3/$1.mp4 --audio_path ../ComfyUI/input/rb3_$2.wav --video_out_path ../rb3/ls/$1_ls${3}.mp4 > /dev/null 2>&1
echo "$1 g${3:-1.5}: $(python -m eval.eval_sync_conf --video_path ../rb3/ls/$1_ls${3}.mp4 2>&1 | grep -A1 confidence | tr '\n' ' ')" >> ../rb3/sync_scores.txt
