<?php
// CWidgetView JSON-encodes this payload; device strings are only rendered via textContent.
(new CWidgetView($data))->setVar('ne_payload', $data['payload'])->show();
