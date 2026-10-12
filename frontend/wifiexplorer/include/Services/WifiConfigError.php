<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Services;

/** A configuration document that failed validation, with every problem found, in words an operator can act on. */
final class WifiConfigError extends \InvalidArgumentException {
    /** @var string[] */
    public array $problems;

    public function __construct(array $problems) {
        parent::__construct('invalid_configuration');
        $this->problems = $problems;
    }
}
