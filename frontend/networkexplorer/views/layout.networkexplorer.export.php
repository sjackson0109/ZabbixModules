<?php
/** Read-only download layout, selected exclusively by the module export route. */
header('Cache-Control: no-store, private');
header('X-Content-Type-Options: nosniff');
header('Content-Type: '.$data['content_type'].'; charset=UTF-8');
header('Content-Disposition: attachment; filename="'.$data['filename'].'"');
http_response_code($data['status_code']);
echo $data['content'];
