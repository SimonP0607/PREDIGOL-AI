# PrediGol's PostgreSQL: the official postgres:16-alpine plus pgBackRest, for continuous WAL archiving and
# point-in-time recovery (PITR) to S3-compatible storage (Cloudflare R2). Nothing secret is in the image: the
# repository's address, keys and cipher passphrase come from the env file at start (predigol-entrypoint).
FROM postgres:16-alpine

# Only for building behind a TLS-inspecting proxy (the rehearsal sandbox): a CA bundle as a BUILD SECRET, used for
# this one step and never written into the image.
RUN --mount=type=secret,id=ca,required=false \
    if [ -s /run/secrets/ca ]; then cp /etc/ssl/certs/ca-certificates.crt /tmp/ca.orig \
      && cat /run/secrets/ca >> /etc/ssl/certs/ca-certificates.crt; fi \
 && apk add --no-cache pgbackrest \
 && if [ -f /tmp/ca.orig ]; then mv /tmp/ca.orig /etc/ssl/certs/ca-certificates.crt; fi \
 && install -d -o postgres -g postgres -m 0750 /var/spool/pgbackrest /var/log/pgbackrest /etc/pgbackrest \
 && pgbackrest version

COPY --chmod=0755 predigol-entrypoint.sh /usr/local/bin/predigol-entrypoint
# The archive_command. Its name must contain "pgbackrest": `pgbackrest check` and `backup` refuse otherwise.
COPY --chmod=0755 pgbackrest-archive-push.sh /usr/local/bin/pgbackrest-archive-push
COPY --chmod=0755 predigol-pitr.sh /usr/local/bin/predigol-pitr

ENTRYPOINT ["predigol-entrypoint"]
CMD ["postgres"]
