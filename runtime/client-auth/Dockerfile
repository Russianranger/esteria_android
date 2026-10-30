# Qualification tools only; never an Android runtime provider. The preceding
# workflow builds this local base from runtime/server's digest/snapshot pins.
FROM esteria-server-reference:qualification
COPY runtime/server/inrelease.SHA256SUMS /opt/esteria-client-auth-inrelease.SHA256SUMS
RUN --mount=type=secret,id=build_ca,required=true,mode=0444 \
    apt-get -o Acquire::https::CaInfo=/run/secrets/build_ca update \
    && (cd /var/lib/apt/lists && sha256sum --check /opt/esteria-client-auth-inrelease.SHA256SUMS) \
    && apt-get -o Acquire::https::CaInfo=/run/secrets/build_ca install -y --no-install-recommends git binutils util-linux iproute2 \
    && dpkg-query -W > /etc/esteria-client-auth-tool-packages.txt \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
CMD ["/usr/bin/python3", "--version"]
