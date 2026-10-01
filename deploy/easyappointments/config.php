<?php
// Runtime-only credentials: bypass the image's plaintext-generating entrypoint.
foreach (['BASE_URL', 'DB_HOST', 'DB_NAME', 'DB_USERNAME', 'DB_PASSWORD'] as $name) {
    $value = getenv($name);
    if ($value === false || $value === '') {
        throw new RuntimeException('Required runtime environment missing: ' . $name);
    }
    define('EA_' . $name, $value);
}

class Config
{
    const BASE_URL = EA_BASE_URL;
    const LANGUAGE = 'english';
    const DEBUG_MODE = false;
    const DB_HOST = EA_DB_HOST;
    const DB_NAME = EA_DB_NAME;
    const DB_USERNAME = EA_DB_USERNAME;
    const DB_PASSWORD = EA_DB_PASSWORD;
    const GOOGLE_SYNC_FEATURE = false;
    const GOOGLE_CLIENT_ID = '';
    const GOOGLE_CLIENT_SECRET = '';
}
