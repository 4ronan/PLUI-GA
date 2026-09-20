<?php
declare(strict_types=1);

const ZT_APP_ROOT = __DIR__ . '/..';

function zt_json_response(int $status, array $payload, array $headers = []): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    header('X-Content-Type-Options: nosniff');
    foreach ($headers as $name => $value) {
        header($name . ': ' . $value);
    }
    echo json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

function zt_load_config(): array
{
    $defaults = [
        'repository' => '4ronan/PLUI-GA',
        'workflow' => 'generate-diagnostic-ovh.yml',
        'ref' => 'main',
        'allowed_origins' => [
            'https://zonage-terrain.fr',
            'https://www.zonage-terrain.fr',
        ],
        'per_ip_per_hour' => 3,
        'global_per_day' => 30,
        'cache_ttl_seconds' => 86400,
    ];
    $documentRoot = rtrim((string)($_SERVER['DOCUMENT_ROOT'] ?? ''), '/');
    $configFile = getenv('ZT_CONFIG_FILE') ?: dirname($documentRoot) . '/private-zonage-terrain/diagnostic.php';
    $custom = [];
    if (is_file($configFile)) {
        $loaded = require $configFile;
        if (is_array($loaded)) {
            $custom = $loaded;
        }
    }
    $config = array_replace($defaults, $custom);
    $envToken = getenv('ZT_GITHUB_TOKEN');
    if (is_string($envToken) && $envToken !== '') {
        $config['github_token'] = $envToken;
    }
    return $config;
}

function zt_require_origin(array $config): void
{
    $origin = (string)($_SERVER['HTTP_ORIGIN'] ?? '');
    if ($origin !== '' && !in_array($origin, $config['allowed_origins'], true)) {
        zt_json_response(403, ['status' => 'failure', 'error' => ['type' => 'origin_rejected', 'message' => 'Origine non autorisée.']]);
    }
}

function zt_runtime_dir(): string
{
    $path = ZT_APP_ROOT . '/runtime';
    if (!is_dir($path) && !mkdir($path, 0700, true) && !is_dir($path)) {
        zt_json_response(503, ['status' => 'failure', 'error' => ['type' => 'storage_unavailable', 'message' => 'Le service ne peut pas enregistrer la demande.']]);
    }
    return $path;
}

function zt_jobs_dir(): string
{
    $path = ZT_APP_ROOT . '/jobs';
    if (!is_dir($path) && !mkdir($path, 0700, true) && !is_dir($path)) {
        zt_json_response(503, ['status' => 'failure', 'error' => ['type' => 'storage_unavailable', 'message' => 'Le service ne peut pas enregistrer le suivi.']]);
    }
    return $path;
}

function zt_atomic_json(string $path, array $payload): void
{
    $temporary = $path . '.' . bin2hex(random_bytes(5)) . '.tmp';
    $encoded = json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT);
    if (file_put_contents($temporary, $encoded, LOCK_EX) === false || !rename($temporary, $path)) {
        @unlink($temporary);
        zt_json_response(503, ['status' => 'failure', 'error' => ['type' => 'storage_unavailable', 'message' => 'Impossible d’enregistrer la demande.']]);
    }
}

function zt_rate_limit(array $config): void
{
    $path = zt_runtime_dir() . '/rate-limit.json';
    $handle = fopen($path, 'c+');
    if ($handle === false || !flock($handle, LOCK_EX)) {
        zt_json_response(503, ['status' => 'failure', 'error' => ['type' => 'rate_limit_unavailable', 'message' => 'Contrôle de charge indisponible.']]);
    }
    $raw = stream_get_contents($handle);
    $state = $raw ? json_decode($raw, true) : [];
    if (!is_array($state)) {
        $state = [];
    }
    $now = time();
    $hourAgo = $now - 3600;
    $dayAgo = $now - 86400;
    $ip = (string)($_SERVER['REMOTE_ADDR'] ?? 'unknown');
    $ipKey = hash('sha256', $ip);
    $state['global'] = array_values(array_filter($state['global'] ?? [], static function ($stamp) use ($dayAgo) {
        return is_int($stamp) && $stamp >= $dayAgo;
    }));
    $state['ips'][$ipKey] = array_values(array_filter($state['ips'][$ipKey] ?? [], static function ($stamp) use ($hourAgo) {
        return is_int($stamp) && $stamp >= $hourAgo;
    }));
    if (count($state['global']) >= (int)$config['global_per_day']) {
        flock($handle, LOCK_UN);
        fclose($handle);
        zt_json_response(429, ['status' => 'failure', 'error' => ['type' => 'daily_limit', 'message' => 'Le quota quotidien de nouveaux diagnostics est atteint. Réessayez demain.']], ['Retry-After' => '3600']);
    }
    if (count($state['ips'][$ipKey]) >= (int)$config['per_ip_per_hour']) {
        flock($handle, LOCK_UN);
        fclose($handle);
        zt_json_response(429, ['status' => 'failure', 'error' => ['type' => 'rate_limit', 'message' => 'Trop de nouveaux diagnostics ont été demandés depuis cette connexion.']], ['Retry-After' => '3600']);
    }
    $state['global'][] = $now;
    $state['ips'][$ipKey][] = $now;
    ftruncate($handle, 0);
    rewind($handle);
    fwrite($handle, json_encode($state));
    fflush($handle);
    flock($handle, LOCK_UN);
    fclose($handle);
}

function zt_job_path(string $jobId): string
{
    return zt_jobs_dir() . '/' . $jobId . '.json';
}

function zt_dispatch_lock()
{
    $handle = fopen(zt_runtime_dir() . '/dispatch.lock', 'c+');
    if ($handle === false || !flock($handle, LOCK_EX)) {
        zt_json_response(503, ['status' => 'failure', 'error' => ['type' => 'dispatch_unavailable', 'message' => 'Le service ne peut pas réserver la génération.']]);
    }
    return $handle;
}

function zt_active_path(string $territory, string $scale): string
{
    return zt_runtime_dir() . '/active-' . $territory . '-' . $scale . '.json';
}
