# Run inside the backend container, which has pyzipper (the library the product reads zips with):
#   tar -C members -c . | docker compose exec -T backend python -I -c "$(cat aes_zip.py)" PASSWORD > out.zip
# Reads a tar of the members on stdin and writes an AES-256 encrypted zip of them to stdout, so no
# file is left in the container. Used by scripts/lib/e2e-zip.sh.
import io
import sys
import tarfile
import warnings

import pyzipper

password = sys.argv[1].encode()
zip_bytes = io.BytesIO()
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    with pyzipper.AESZipFile(zip_bytes, "w", compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES) as archive:
        archive.setpassword(password)
        with tarfile.open(fileobj=sys.stdin.buffer, mode="r|") as members:
            for member in members:
                if member.isfile():
                    archive.writestr(member.name.removeprefix("./"), members.extractfile(member).read())
sys.stdout.buffer.write(zip_bytes.getvalue())
