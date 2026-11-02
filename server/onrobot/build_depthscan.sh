cd /mnt/c/Claude/Lucy_Control_Server/onrobot && aarch64-linux-gnu-gcc -static -O2 -o depthscan depthscan.c -lm 2>&1 | grep -i error; ls -l depthscan
