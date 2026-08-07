# WAI Telegram production cutover

Production is a closed, single-owner service. Direct `deploy.sh` and automatic
rollback are disabled. Deploy only from `main` through the manual **CI / Deploy**
workflow and its protected `production` environment.

## Provider prerequisites

- Resize the server to at least 4 CPU and 8 GB RAM.
- Attach a 500 GB-class Hetzner Volume. Resolve its stable
  `/dev/disk/by-id/...` path, then run `scripts/mount-media-volume.sh --device
  <path> --format-empty-volume`. Omit `--format-empty-volume` for a volume that
  already contains a filesystem.
- Confirm `findmnt /srv/wai-telegram-media` reports the expected volume UUID.
- Create a private NBG1 Object Storage bucket and `/etc/wai-telegram/restic.env`
  from `config/restic.env.example`; store the restic password in a root-readable
  file with mode `0600`.
- Add `OWNER_USER_ID` to `/opt/wai-telegram/.env.production`. Store the separate
  cutover-dump passphrase in `/etc/wai-telegram/auth-backup-passphrase` with mode
  `0600`, owned by root, and keep an off-server copy.
- Initialize and verify the repository with `scripts/restic-init.sh`.

The normal `media_mode=full` workflow refuses to continue if CPU, memory, media
mount, media volume size, restic configuration, or required owner credentials
are missing. A temporary `media_mode=deferred` release is allowed only with
`MEDIA_PIPELINE_ENABLED=false`, the cloud Bot API URL, at least 2 CPU / 3.5 GB
RAM / 8 GB free root storage, and a verified encrypted database backup. It does
not start media workers, local Bot API, reconciliation, or restic timers.

## Cutover guarantees

Before changing code or stopping services, the workflow creates an
authenticated GPG-encrypted custom-format PostgreSQL dump, verifies both the
plain and decrypted copies with `pg_restore --list`, and then runs an off-host
Restic backup that includes the cutover dump and media volume.

The owner dry-run must identify the same `OWNER_USER_ID` from all three signals:
the only active Telegram session, a recently used active API key, and the largest
message archive. Any ambiguity stops before database mutation. Applying the
cutover deactivates every other user and access path while preserving their
chats, messages, transcripts, and metadata under their original user IDs.

## Deploy

1. For the one-time account transition, run `CI / Deploy` from `main` with
   `deployment_mode=initial-cutover`. Select `media_mode=full` after the target
   infrastructure exists, or `media_mode=deferred` for an explicit auth-only
   cutover on the constrained host. All later releases use
   `deployment_mode=standard`; they validate the existing owner and never repeat
   deactivation timestamps or Telegram revocations.
2. The separate read-only preflight job prints the owner evidence before the
   protected environment waits for approval. Keep the SSH host/key/known-hosts
   secrets at repository scope so this preflight can run without production
   environment access. Approve only after reviewing CI and that output.
3. The workflow installs the local Bot API, performs the explicit cloud-to-local
   bot logout/webhook cutover, starts the split media workers, verifies public
   health and MCP authentication, then starts checkpointed search-index and
   metadata-only reconciliation jobs.
4. Check `systemctl status wai-search-indexes wai-metadata-reconcile` until both
   oneshots finish successfully. No historical media bytes are downloaded by
   either job.
5. Run `systemctl start wai-restic-backup` and wait for success before treating
   media backup as established. Weekly checks and quarterly actual database
   restore drills then run by timer.

In deferred mode, `prepare_media` returns `media_pipeline_deferred` and direct
small bot media continues through Telegram's cloud Bot API using ephemeral temp
files. This is a visible operational state, not a fallback. Enable full mode only
after attaching durable storage and completing the local Bot API/restic setup.

## Recovery boundary

Do not deploy old code or downgrade migration `019_single_user_mode`: that would
remove the active-user guard and can reopen registration/access. First preserve
the failed release and collect service/database evidence. A rollback decision
must explicitly choose whether to retain the single-owner auth state or restore
the encrypted pre-cutover database. Only then restore a selected release backup
and database dump in a maintenance window, verify owner access, verify archived
counts, and reopen traffic.

## Live acceptance

Use the owner's Saved Messages and private WAI bot chat to test photo, document,
scanned PDF, voice, audio, video, silent video, video note, and a bot file larger
than 20 MB. Through production MCP, fully download the known multi-GB object,
verify SHA-256, `HEAD`, `Range: bytes=...` returning `206`, resume, and a refreshed
signed URL. Confirm the same message IDs for filename, hidden URL, and transcript
phrase searches in MCP, Telegram WAI, and a scheduled agent. Monitor queues,
cache, disk, FloodWait, auth failures, and Sentry without PII for 24 hours.
