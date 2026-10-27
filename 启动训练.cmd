@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 1846 自学习训练：默认 6 个自战进程，低于正常优先级运行。
echo 关闭此窗口会结束训练（模型与数据已保存在 train\ 下）。
python train\orchestrate.py --workers 6 --minutes 240 --train-every 4 --steps 200 --eval-every 30
pause
