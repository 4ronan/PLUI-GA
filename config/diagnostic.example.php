<?php
return [
    // Jeton GitHub à permissions minimales : dépôt PLUI-GA, Actions en écriture.
    'github_token' => '', // Renseigner uniquement dans la copie privée sur OVH.
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
