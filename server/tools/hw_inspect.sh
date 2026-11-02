echo "== USB devices"
for d in /sys/bus/usb/devices/*; do
  [ -f "$d/idVendor" ] && echo "$(basename $d) $(cat $d/idVendor):$(cat $d/idProduct) $(cat $d/manufacturer 2>/dev/null) $(cat $d/product 2>/dev/null) speed=$(cat $d/speed 2>/dev/null)"
done
echo "== USB controllers / OTG role"
ls /sys/class/udc 2>/dev/null; cat /sys/devices/platform/*usb*/*/mode 2>/dev/null | head -3
grep -i -E 'usb|otg|dwc' /proc/interrupts | head -5
echo "== Bluetooth / Wi-Fi radios"
ls /sys/class/bluetooth 2>/dev/null; ls /sys/class/rfkill 2>/dev/null && for r in /sys/class/rfkill/rfkill*; do echo "$r $(cat $r/type) $(cat $r/name) state=$(cat $r/state)"; done
which hciconfig hcitool bluetoothctl btmgmt 2>/dev/null
getprop 2>/dev/null | grep -i -E 'bluetooth|bt\.|wifi.chip|wlan' | head -8
lsmod 2>/dev/null | grep -i -E 'bt|blue|wlan|8723|8821|bcm|rtl' | head
cat /proc/cpuinfo | grep -i -E 'hardware|model name' | head -2
