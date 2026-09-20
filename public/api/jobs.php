<?php
declare(strict_types=1);
require __DIR__ . '/bootstrap.php';

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'GET') {
    header('Allow: GET');
    zt_json_response(405, ['status' => 'failure', 'error' => ['type' => 'method_not_allowed', 'message' => 'Utilisez une requête GET.']]);
}
$jobId = strtolower(trim((string)($_GET['id'] ?? '')));
if (!preg_match('/^[a-f0-9]{32}$/', $jobId)) {
    zt_json_response(400, ['status' => 'failure', 'error' => ['type' => 'invalid_job', 'message' => 'Identifiant de demande invalide.']]);
}
$path = zt_job_path($jobId);
if (!is_file($path)) {
    zt_json_response(404, ['status' => 'failure', 'error' => ['type' => 'job_not_found', 'message' => 'Demande inconnue ou expirée.']]);
}
$job = json_decode((string)file_get_contents($path), true);
if (!is_array($job)) {
    zt_json_response(500, ['status' => 'failure', 'error' => ['type' => 'job_corrupted', 'message' => 'Le suivi de la demande est illisible.']]);
}
if (($job['status'] ?? '') === 'queued') {
    $created = strtotime((string)($job['created_at'] ?? '')) ?: time();
    if ($created < time() - 2700) {
        $job['status'] = 'failure';
        $job['finished_at'] = gmdate('c');
        $job['error'] = ['type' => 'generation_timeout', 'message' => 'La génération n’a pas abouti dans le délai prévu.'];
        zt_atomic_json($path, $job);
    }
}
zt_json_response(200, $job, in_array(($job['status'] ?? ''), ['queued', 'running'], true) ? ['Retry-After' => '3'] : []);
