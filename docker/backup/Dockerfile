# Backup service: same PostgreSQL major version as the db service (pg_dump must match), plus gnupg
# (optional encryption) and rclone (optional off-site copy). See docs/SAUVEGARDES.md.
FROM postgres:17-alpine

RUN apk add --no-cache bash coreutils findutils tar gzip gnupg rclone tzdata util-linux

COPY docker/backup/lib.sh /usr/local/bin/backup-lib.sh
COPY docker/backup/backup.sh /usr/local/bin/backup.sh
COPY docker/backup/restore.sh /usr/local/bin/restore.sh
COPY docker/backup/verify.sh /usr/local/bin/verify.sh
COPY docker/backup/list.sh /usr/local/bin/list.sh
COPY docker/backup/healthcheck.sh /usr/local/bin/backup-healthcheck.sh
COPY docker/backup/entrypoint.sh /usr/local/bin/backup-entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/*.sh && chmod 755 /usr/local/bin/*.sh

ENV TZ=Africa/Douala BACKUP_ROOT=/backups MEDIA_DIR=/media
HEALTHCHECK --interval=5m --timeout=10s --start-period=10m CMD ["/usr/local/bin/backup-healthcheck.sh"]
ENTRYPOINT ["/usr/local/bin/backup-entrypoint.sh"]
