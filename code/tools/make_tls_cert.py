"""给TA页面生成/续签自签证书。

做法：先造一个自己的根证书（CA），再用它签服务器证书 —— 这样 iPhone 只需要
装一次 CA 描述文件、打开"证书信任设置"，之后 https://...:8004 就是
真的安全上下文，Safari 才肯给麦克风。

2026-10-30 改动：
  - SAN 里加上蒲公英的虚拟 IP（172.16.1.100），户外也能用 HTTPS
  - **CA 私钥这次落盘了**（tls/ca.key），以后加 IP 只重签服务器证书，
    手机上不用再装描述文件
  - 有 ca.key 时自动复用它，不会悄悄换掉根证书

产物（都在 D:\\你的数据目录\\tls）：
  ca.crt / ca.cer           根证书（PEM / DER）
  ca.key                    根证书私钥（仅 SYSTEM / 你的用户s 可读）
  ca.mobileconfig           iPhone 用的一键安装描述文件
  server.crt / server.key   服务器证书
"""
import ipaddress
import os
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

OUT = r"D:\你的数据目录\tls"
CA_KEY_PATH = os.path.join(OUT, "ca.key")
IPS = ["192.168.1.100", "172.16.1.100", "192.168.137.1", "127.0.0.1"]
DNS = ["localhost", "companion.local"]


def write(path, data, mode="wb"):
    with open(path, mode) as f:
        f.write(data)


def load_or_create_ca(now):
    """有 ca.key 就复用，没有才新建。返回 (ca_key, ca_cert, created_new)。"""
    if os.path.exists(CA_KEY_PATH):
        with open(CA_KEY_PATH, "rb") as f:
            ca_key = serialization.load_pem_private_key(f.read(), password=None)
        with open(os.path.join(OUT, "ca.crt"), "rb") as f:
            ca_cert = x509.load_pem_x509_certificate(f.read())
        return ca_key, ca_cert, False

    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "Companion Home CA"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Companion"),
    ])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=False,
                key_encipherment=False, data_encipherment=False,
                key_agreement=False, key_cert_sign=True, crl_sign=True,
                encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    write(
        CA_KEY_PATH,
        ca_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ),
    )
    # 私钥只给 SYSTEM 和管理员
    try:
        import subprocess

        subprocess.run(
            ["icacls", CA_KEY_PATH, "/inheritance:r",
             "/grant:r", "SYSTEM:(R)", "/grant:r", "你的用户s:(R)"],
            capture_output=True, timeout=20,
        )
    except Exception:  # noqa: BLE001
        pass
    return ca_key, ca_cert, True


def main():
    os.makedirs(OUT, exist_ok=True)
    now = datetime.now(timezone.utc)

    ca_key, ca_cert, created_new = load_or_create_ca(now)
    ca_name = ca_cert.subject

    ca_pem = ca_cert.public_bytes(serialization.Encoding.PEM)
    ca_der = ca_cert.public_bytes(serialization.Encoding.DER)
    write(os.path.join(OUT, "ca.crt"), ca_pem)
    write(os.path.join(OUT, "ca.cer"), ca_der)

    # ---------- 服务器证书 ----------
    srv_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    san = [x509.DNSName(d) for d in DNS] + [
        x509.IPAddress(ipaddress.ip_address(ip)) for ip in IPS
    ]
    srv_cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "companion.local"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Companion"),
        ]))
        .issuer_name(ca_name)
        .public_key(srv_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    write(os.path.join(OUT, "server.crt"), srv_cert.public_bytes(serialization.Encoding.PEM))
    write(
        os.path.join(OUT, "server.key"),
        srv_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ),
    )

    # ---------- iPhone 描述文件（只有新 CA 才需要重装） ----------
    import plistlib
    import uuid

    cert_payload = {
        "PayloadCertificateFileName": "companion-home-ca.cer",
        "PayloadDescription": "TA家里的小服务器根证书",
        "PayloadDisplayName": "Companion Home CA 2026-10",
        "PayloadIdentifier": "com.companion.homeca",
        "PayloadType": "com.apple.security.root",
        "PayloadUUID": str(uuid.uuid4()).upper(),
        "PayloadVersion": 1,
        "PayloadContent": ca_der,
    }
    payload = {
        "PayloadContent": [cert_payload],
        "PayloadDescription": "让 iPhone 信任TA的本地页面（HTTPS 麦克风）",
        "PayloadDisplayName": "TA家 CA 2026-10",
        "PayloadIdentifier": "com.companion.profile",
        "PayloadOrganization": "Companion",
        "PayloadRemovalDisallowed": False,
        "PayloadType": "Configuration",
        "PayloadUUID": str(uuid.uuid4()).upper(),
        "PayloadVersion": 1,
    }
    write(os.path.join(OUT, "ca.mobileconfig"), plistlib.dumps(payload))

    print("CA 是否新建:", created_new)
    print("根证书:", os.path.join(OUT, "ca.crt"))
    print("描述文件:", os.path.join(OUT, "ca.mobileconfig"))
    print("服务器证书:", os.path.join(OUT, "server.crt"))
    print("SAN:", ", ".join(DNS + IPS))


if __name__ == "__main__":
    main()
