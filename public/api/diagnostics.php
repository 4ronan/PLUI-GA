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
$resultUrl = 'diagnostics/' . $territory . '/';
$diagnosticPath = ZT_APP_ROOT . '/diagnostics/' . $territory . '/diagnostic.json';
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
    $created = is_array($activeJob) ? (strtotime((string)($activeJob['created_at'] ?? '')) ?: 0) : 0;
    if (is_array($activeJob) && in_array(($activeJob['status'] ?? ''), ['queued', 'running'], true) && $created >= time() - 2700) {
        $statusUrl = 'api/jobs.php?id=' . $activeJob['id'];
        zt_json_response(202, $activeJob + ['deduplicated' => true, 'status_url' => $statusUrl], ['Location' => $statusUrl]);
    }
}

if (empty($config['github_token']) || !is_string($config['github_token'])) {
    zt_json_response(503, ['status' => 'failure', 'error' => ['type' => 'configuration_missing', 'message' => 'Le moteur de génération n’est pas encore activé.']]);
}
zt_rate_limit($config);
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

$repository = trim((string)$config['repository'], '/');
if (!preg_match('#^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$#', $repository)) {
    zt_json_response(503, ['status' => 'failure', 'error' => ['type' => 'configuration_invalid', 'message' => 'Configuration du dépôt invalide.']]);
}
$url = 'https://api.github.com/repos/' . $repository . '/actions/workflows/' . rawurlencode((string)$config['workflow']) . '/dispatches';
$body = json_encode([
    'ref' => (string)$config['ref'],
    'inputs' => ['territory' => $territory, 'scale' => $scale, 'request_id' => $jobId],
]);
if (!function_exists('curl_init')) {
    $job['status'] = 'failure';
    $job['finished_at'] = gmdate('c');
    $job['error'] = ['type' => 'configuration_missing', 'message' => 'L’extension PHP cURL doit être activée.'];
    zt_atomic_json(zt_job_path($jobId), $job);
    zt_json_response(503, $job);
}
$curl = curl_init($url);
curl_setopt_array($curl, [
    CURLOPT_POST => true,
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_CONNECTTIMEOUT => 10,
    CURLOPT_TIMEOUT => 25,
    CURLOPT_HTTPHEADER => [
        'Accept: application/vnd.github+json',
        'Authorization: Bearer ' . $config['github_token'],
        'Content-Type: application/json',
        'User-Agent: zonage-terrain-vacance',
        'X-GitHub-Api-Version: 2022-11-28',
    ],
    CURLOPT_POSTFIELDS => $body,
]);
curl_exec($curl);
$status = (int)curl_getinfo($curl, CURLINFO_RESPONSE_CODE);
$error = curl_error($curl);
curl_close($curl);
if ($status !== 204) {
    $job['status'] = 'failure';
    $job['finished_at'] = gmdate('c');
    $job['error'] = ['type' => 'dispatch_failure', 'message' => 'La génération n’a pas pu être lancée.'];
    zt_atomic_json(zt_job_path($jobId), $job);
    error_log('GitHub dispatch failure HTTP ' . $status . ' ' . $error);
    zt_json_response(502, $job);
}

$statusUrl = 'api/jobs.php?id=' . $jobId;
zt_json_response(202, $job + ['status_url' => $statusUrl], ['Location' => $statusUrl]);
