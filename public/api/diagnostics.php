<?php
declare(strict_types=1);
require __DIR__ . '/bootstrap.php';

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    header('Allow: POST');
    zt_json_response(405, ['status' => 'failure', 'error' => ['type' => 'method_not_allowed', 'message' => 'Utilisez une requête POST.']]);
}

$config = zt_load_config();
zt_require_origin($config);
$length = (int)($_SERVER['CONTENT_LENGTH'] ?? 0);
if ($length <= 0 || $length > 4096) {
    zt_json_response(400, ['status' => 'failure', 'error' => ['type' => 'invalid_body', 'message' => 'Corps JSON absent ou trop volumineux.']]);
}
$payload = json_decode((string)file_get_contents('php://input'), true);
if (!is_array($payload)) {
    zt_json_response(400, ['status' => 'failure', 'error' => ['type' => 'invalid_json', 'message' => 'Corps JSON invalide.']]);
}
$territory = strtoupper(trim((string)($payload['territory'] ?? $payload['code'] ?? '')));
$scale = strtolower(trim((string)($payload['scale'] ?? '')));
if (!preg_match('/^[0-9A-Z]{5}$/', $territory)) {
    zt_json_response(400, ['status' => 'failure', 'error' => ['type' => 'invalid_territory', 'message' => 'Code INSEE communal invalide.']]);
}
if (!in_array($scale, ['department', 'region', 'france'], true)) {
    zt_json_response(400, ['status' => 'failure', 'error' => ['type' => 'invalid_scale', 'message' => 'Échelle de comparaison invalide.']]);
}

$dispatchLock = zt_dispatch_lock();
$resultUrl = 'diagnostics/' . $territory . '/' . $scale . '/';
$diagnosticPath = ZT_APP_ROOT . '/diagnostics/' . $territory . '/' . $scale . '/diagnostic.json';
$cacheValid = is_file($diagnosticPath) && filemtime($diagnosticPath) >= time() - (int)$config['cache_ttl_seconds'];
if ($cacheValid) {
    $jobId = bin2hex(random_bytes(16));
    $job = [
        'id' => $jobId,
        'status' => 'success',
        'territory' => $territory,
        'scale' => $scale,
        'cached' => true,
        'finished_at' => gmdate('c'),
        'result_url' => $resultUrl,
    ];
    zt_atomic_json(zt_job_path($jobId), $job);
    zt_json_response(200, $job + ['status_url' => 'api/jobs.php?id=' . $jobId]);
}

$activePath = zt_active_path($territory, $scale);
$active = is_file($activePath) ? json_decode((string)file_get_contents($activePath), true) : null;
if (is_array($active) && preg_match('/^[a-f0-9]{32}$/', (string)($active['id'] ?? ''))) {
    $activeJobPath = zt_job_path((string)$active['id']);
    $activeJob = is_file($activeJobPath) ? json_decode((string)file_get_contents($activeJobPath), true) : null;
    $reference = is_array($activeJob) && ($activeJob['status'] ?? '') === 'running'
        ? ($activeJob['started_at'] ?? $activeJob['created_at'] ?? '')
        : ($activeJob['created_at'] ?? '');
    $created = is_array($activeJob) ? (strtotime((string)$reference) ?: 0) : 0;
    if (is_array($activeJob) && in_array(($activeJob['status'] ?? ''), ['queued', 'running'], true) && $created >= time() - (int)$config['job_timeout_seconds']) {
        $statusUrl = 'api/jobs.php?id=' . $activeJob['id'];
        zt_json_response(202, $activeJob + ['deduplicated' => true, 'status_url' => $statusUrl], ['Location' => $statusUrl]);
    }
}

zt_rate_limit($config);
$queueDir = zt_queue_dir();
$queuedFiles = glob($queueDir . '/*.json');
if (is_array($queuedFiles) && count($queuedFiles) >= (int)$config['queue_max']) {
    zt_json_response(503, ['status' => 'failure', 'error' => ['type' => 'queue_full', 'message' => 'Le service reçoit temporairement trop de demandes. Réessayez plus tard.']]);
}
$jobId = bin2hex(random_bytes(16));
$job = [
    'id' => $jobId,
    'status' => 'queued',
    'territory' => $territory,
    'scale' => $scale,
    'cached' => false,
    'created_at' => gmdate('c'),
];
zt_atomic_json(zt_job_path($jobId), $job);
zt_atomic_json($activePath, ['id' => $jobId, 'created_at' => $job['created_at']]);
zt_atomic_json($queueDir . '/' . $jobId . '.json', [
    'id' => $jobId,
    'territory' => $territory,
    'scale' => $scale,
    'created_at' => $job['created_at'],
]);

$statusUrl = 'api/jobs.php?id=' . $jobId;
zt_json_response(202, $job + ['status_url' => $statusUrl], ['Location' => $statusUrl]);
