<?php
namespace Modules\NeTopology\Actions;
use API;
use CControllerDashboardWidgetView;
use CControllerResponseData;
use Modules\NetworkExplorer\Services\NetworkService;

class WidgetView extends CControllerDashboardWidgetView {
 protected function doAction(): void {
  $payload = ['hosts'=>[], 'interfaces'=>[], 'edges'=>[], 'lags'=>[], 'quality'=>[], 'findings'=>[]];
  $hostid = (string) ($this->fields_values['override_hostid'][0] ?? '');
  $uid = substr((string) ($this->fields_values['interface_uid'] ?? ''), 0, 128);
  $itemid = (string) ($this->fields_values['itemid'][0] ?? '');
  $cidr = substr(trim((string) ($this->fields_values['management_cidr'] ?? '')), 0, 128);
  $layout = [0=>'auto',1=>'24',2=>'48',3=>'mixed',4=>'stack',5=>'generic'][(int) ($this->fields_values['layout'] ?? 0)] ?? 'auto';
  $payload['scope'] = array_replace($payload['scope'] ?? [], ['hostid'=>$hostid, 'interface_uid'=>$uid, 'itemid'=>$itemid,
   'management_cidr'=>$cidr, 'layout'=>$layout]);
  try {
   $autoload = dirname(__DIR__, 2).'/networkexplorer/include/autoload.php';
   if (!is_file($autoload)) throw new \RuntimeException('Install and enable the Network Explorer base module.');
   require_once $autoload;
   if ($hostid !== '' && !preg_match('/^[1-9][0-9]*$/D', $hostid)) throw new \RuntimeException('Invalid host selection.');
   if ($itemid !== '') {
    if (!preg_match('/^[1-9][0-9]*$/D', $itemid)) throw new \RuntimeException('Invalid item selection.');
    $items = API::Item()->get(['output'=>['itemid','hostid','key_'], 'itemids'=>[$itemid]]);
    if (!$items) throw new \RuntimeException('The selected interface item is unavailable or inaccessible.');
    $item = reset($items);
    if (!preg_match('/^ne\.if\.oper\[([^\]\r\n]{1,128})\]$/D', $item['key_'], $matches)) {
     throw new \RuntimeException('Select a Network Explorer interface operational item.');
    }
    if ($hostid !== '' && $hostid !== (string) $item['hostid']) throw new \RuntimeException('The selected item belongs to a different host.');
    $hostid = (string) $item['hostid'];
    $uid = trim($matches[1], '"');
   }
   $needs_host = false;
   if ($hostid === '' && ($needs_host || $this->isTemplateDashboard())) {
    $payload['message'] = 'Select a host using the widget configuration or Host navigator.';
   }
   else {
    $payload = NetworkService::create()->build($hostid === '' ? [] : [$hostid], $cidr);
   }
   $payload['scope'] = array_replace($payload['scope'] ?? [], ['hostid'=>$hostid, 'interface_uid'=>$uid, 'itemid'=>$itemid,
    'management_cidr'=>$cidr, 'layout'=>$layout]);
  }
  catch (\Throwable $e) {
   // Never reflect API/history exception text or device-reported values into diagnostics.
   $messages = [
    'Install and enable the Network Explorer base module.' => 'Install and enable the Network Explorer base module.',
    'Invalid host selection.' => 'Invalid host selection.',
    'Invalid item selection.' => 'Invalid item selection.',
    'The selected interface item is unavailable or inaccessible.' => 'The selected interface item is unavailable or inaccessible.',
    'Select a Network Explorer interface operational item.' => 'Select a Network Explorer interface operational item.',
    'The selected item belongs to a different host.' => 'The selected item belongs to a different host.',
    'invalid_management_cidr' => 'Enter valid IPv4 or IPv6 management subnet ranges.',
    'host_budget_exceeded' => 'The host scope exceeds the 300-host limit. Select a narrower scope.',
    'interface_budget_exceeded' => 'The interface scope exceeds the reader limit. Select a narrower scope.',
    'history_budget_exceeded' => 'The history request exceeds the reader limit. Select a narrower scope.'
   ];
   $payload['message'] = $messages[$e->getMessage()]
    ?? 'Network observations could not be loaded. Check module installation and server diagnostics.';
  }
  $this->setResponse(new CControllerResponseData([
   'name'=>$this->getInput('name', $this->widget->getDefaultName()),
   'user'=>['debug_mode'=>$this->getDebugMode()], 'payload'=>$payload
  ]));
 }
}
