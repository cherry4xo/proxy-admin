from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.database.base import Base


class SSHKey(Base):
    __tablename__ = "ssh_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    public_key: Mapped[str] = mapped_column(String, nullable=False)
    # PEM-формат, зашифрован Fernet (ENCRYPTION_KEY из .env)
    private_key_encrypted: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    nodes: Mapped[list["Node"]] = relationship("Node", back_populates="ssh_key")


class Node(Base):
    __tablename__ = "nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role: Mapped[str] = mapped_column(String, nullable=False)       # "bridge" | "exit"
    provider: Mapped[str] = mapped_column(String, nullable=False)   # "bitlaunch" | "yandex"
    provider_id: Mapped[str] = mapped_column(String, nullable=False)  # ID у провайдера
    name: Mapped[str] = mapped_column(String, nullable=False)
    ip: Mapped[str | None] = mapped_column(String, nullable=True)
    ssh_port: Mapped[int] = mapped_column(Integer, default=22)

    ssh_key_id: Mapped[int] = mapped_column(ForeignKey("ssh_keys.id"), nullable=False)
    ssh_key: Mapped[SSHKey] = relationship("SSHKey", back_populates="nodes")

    # REALITY / X25519 (для Exit Node, а с двухплечевым bridge — и для Bridge Node; зашифровано Fernet)
    x25519_private_encrypted: Mapped[str | None] = mapped_column(String, nullable=True)
    x25519_public: Mapped[str | None] = mapped_column(String, nullable=True)
    short_id: Mapped[str | None] = mapped_column(String, nullable=True)
    reality_sni: Mapped[str | None] = mapped_column(String, nullable=True)

    # Bridge-only: единый VLESS uuid, которым Bridge аутентифицируется на Exit.
    bridge_uuid: Mapped[str | None] = mapped_column(String, nullable=True)

    # Bridge-only: если задан — клиент-плечо REALITY маскируется под СВОЙ домен
    # (локальный nginx :8443 как dest), serverName=reality_sni=этот домен.
    # NULL => легаси (www.microsoft.com, dest=<sni>:443).
    reality_domain: Mapped[str | None] = mapped_column(String, nullable=True)

    xray_api_port: Mapped[int] = mapped_column(Integer, default=8080)
    status: Mapped[str] = mapped_column(String, default="provisioning")
    # "provisioning" | "active" | "blocked" | "deleting"

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Bridge → Exit связи (M:N)
    exit_links: Mapped[list["NodeLink"]] = relationship(
        "NodeLink", foreign_keys="NodeLink.bridge_id", back_populates="bridge"
    )
    bridge_links: Mapped[list["NodeLink"]] = relationship(
        "NodeLink", foreign_keys="NodeLink.exit_id", back_populates="exit"
    )

    users: Mapped[list["User"]] = relationship("User", back_populates="exit_node")


class NodeLink(Base):
    __tablename__ = "node_links"
    __table_args__ = (UniqueConstraint("bridge_id", "exit_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bridge_id: Mapped[int] = mapped_column(ForeignKey("nodes.id"), nullable=False)
    exit_id: Mapped[int] = mapped_column(ForeignKey("nodes.id"), nullable=False)

    bridge: Mapped[Node] = relationship("Node", foreign_keys=[bridge_id], back_populates="exit_links")
    exit: Mapped[Node] = relationship("Node", foreign_keys=[exit_id], back_populates="bridge_links")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    uuid: Mapped[str] = mapped_column(String, unique=True, nullable=False)

    exit_node_id: Mapped[int] = mapped_column(ForeignKey("nodes.id"), nullable=False)
    exit_node: Mapped[Node] = relationship("Node", back_populates="users")

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Certificate(Base):
    __tablename__ = "certificates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    # PEM, зашифрованы Fernet (ENCRYPTION_KEY из .env) — один общий серт на домен,
    # раскладывается по всем bridge-нодам этого домена.
    fullchain_encrypted: Mapped[str] = mapped_column(String, nullable=False)
    privkey_encrypted: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
