/**
 * nettap-web's writable volume (web-data; the container is read_only): users, the JWT secret, the
 * setup code and the in-app notifications. One name, so moving it moves them all (NET-224 review L4).
 */
export const DATA_DIR = process.env.DATA_DIR || '/var/lib/nettap-web';
