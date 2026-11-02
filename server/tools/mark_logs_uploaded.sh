cd /data/user/app
cp -p data.db /data/lucy_local/data.db.bak_$(date +%Y%m%d_%H%M%S)
ls -l /data/lucy_local/ | grep data.db
sqlite3 data.db "UPDATE tb_split_log SET upload_flag = 1, upload_result = 'marked uploaded locally 2026-10-15' WHERE upload_flag = 0"
sqlite3 data.db 'select path, upload_flag, upload_result from tb_split_log'
