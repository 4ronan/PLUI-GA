<?php
return [
    'allowed_origins' => [
        'https://zonage-terrain.fr',
        'https://www.zonage-terrain.fr',
    ],
    'per_ip_per_hour' => 3,
    'global_per_day' => 30,
    'cache_ttl_seconds' => 86400,
    'job_timeout_seconds' => 7200,
    'queue_max' => 100,
];
