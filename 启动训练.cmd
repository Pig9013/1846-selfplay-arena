@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 1846 持续自学习：默认 6 个自战进程，低于正常优先级运行。
echo 不关闭此窗口、不按 Ctrl+C 就会一直自战；每 1000 局自动生成行动逻辑分析。
echo 关闭此窗口会停止训练（模型、样本与分析已保存在 train\ 下）。
python train\orchestrate.py --workers 6 --report-every 1000 --eval-every 300 --keep 4000
pause
