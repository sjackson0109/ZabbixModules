<?php
declare(strict_types=1);
namespace Modules\NetworkExplorer\Actions;

use Modules\NetworkExplorer\Services\ReportService;

final class Export extends Base {
    protected function doAction(): void {
        $report = $this->getInput('report', 'inventory');
        $format = $this->getInput('format', 'json');
        try {
            if (!in_array($format, ['json','csv'], true)) {
                throw new \InvalidArgumentException('invalid_format');
            }
            $network = $this->network();
            // An oversized scope is never exported as if it were empty.
            if (isset($network['scope']['oversized'])) {
                throw new \InvalidArgumentException('scope_oversized');
            }
            $service = new ReportService();
            $rows = $service->rows($network, $report);
            $content = $format === 'csv' ? $service->csv($service->contextualRows($network, $report)) : json_encode([
                'schema_version'=>$network['schema_version'],'generated_at'=>$network['generated_at'], 'report'=>$report,
                'scope'=>$network['scope'],'coverage'=>$network['quality'],'rows'=>$rows
            ], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_INVALID_UTF8_SUBSTITUTE
                | JSON_THROW_ON_ERROR);
            $data = ['content'=>$content, 'content_type'=>$format === 'csv' ? 'text/csv' : 'application/json',
                'filename'=>'network-explorer-'.$report.'.'.$format, 'status_code'=>200];
        }
        catch (\Throwable $error) {
            $data = ['content'=>json_encode($this->error($error)), 'content_type'=>'application/json',
                'filename'=>'network-explorer-error.json', 'status_code'=>400];
        }
        $this->setResponse((new \CControllerResponseData($data))->disableView());
    }
}
