# Test-only overlay; never an application/runtime provider.
FROM esteria-server-reference:qualification
COPY debs /opt/esteria-auth-tools/debs
COPY tool-inputs.lock.json verify.py /opt/esteria-auth-tools/
RUN --network=none python3 /opt/esteria-auth-tools/verify.py --lock /opt/esteria-auth-tools/tool-inputs.lock.json --archives /opt/esteria-auth-tools/debs --before /opt/esteria-auth-tools/before.json \
    && DEBIAN_FRONTEND=noninteractive dpkg -i /opt/esteria-auth-tools/debs/*.deb \
    && python3 /opt/esteria-auth-tools/verify.py --lock /opt/esteria-auth-tools/tool-inputs.lock.json --before /opt/esteria-auth-tools/before.json --receipt /etc/esteria-client-auth-tools.json \
    && dpkg-query -W > /etc/esteria-client-auth-tool-packages.txt \
    && rm -rf /opt/esteria-auth-tools/debs
CMD ["/usr/bin/python3", "--version"]
