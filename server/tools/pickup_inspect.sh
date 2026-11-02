cd /data/user/app/log
echo "== cloud: mode switches / reloc tonight"
grep -a -h -E 'NeedReloc|RELOC|reloc|kidnap|lift|wheel' $(ls -t cloud_node.localhost*ERROR* | head -1) | grep -a -E 'E1014 23:(1|2|3|4)' | cut -c1-170 | head -20
echo "== guidance / sensor: lift, drop, kidnap"
grep -a -h -i -E 'kidnap|lift|wheel_drop|wheel drop|pick|reloc' guidance_node.localhost.root.log.ERROR.20210128-115257.1290 | grep -a -E 'E1014 2[23]:' | cut -c1-170 | tail -15
echo "== slam: reloc"
f=$(ls -t slam_node.localhost*ERROR* | head -1); echo $f
grep -a -h -i -E 'reloc|kidnap|lost|track' $f | tail -12 | cut -c1-170
