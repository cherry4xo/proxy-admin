import pytest

from bot.services.ssh import SSHClient, _CONFIG_PATH, _SYSTEMD_RESTART_CMD


@pytest.fixture()
def encrypted_key(fernet_key: str) -> str:
    from cryptography.fernet import Fernet
    from bot.services.keygen import generate_ssh_keypair

    private_pem, _ = generate_ssh_keypair()
    return Fernet(fernet_key.encode()).encrypt(private_pem.encode()).decode()


@pytest.fixture()
def ssh_client(encrypted_key: str, mocker) -> SSHClient:
    mocker.patch("bot.services.ssh.decrypt", return_value="-----BEGIN OPENSSH PRIVATE KEY-----\nfake\n-----END OPENSSH PRIVATE KEY-----")
    return SSHClient(host="1.2.3.4", port=22, private_key_pem_encrypted=encrypted_key)


@pytest.fixture()
def _mock_upload(ssh_client: SSHClient, mocker):
    mocker.patch.object(ssh_client, "upload_file")


@pytest.fixture()
def _mock_run(ssh_client: SSHClient, mocker):
    # Валидный конфиг: xray -test печатает "Configuration OK".
    mocker.patch.object(ssh_client, "run_command", return_value=("Configuration OK", ""))


@pytest.mark.asyncio
@pytest.mark.usefixtures("_mock_upload", "_mock_run")
async def test_deploy_xray_config_tests_then_restarts(ssh_client: SSHClient):
    await ssh_client.deploy_xray_config("{}", xray_runtime="systemd")

    calls = [c.args[0] for c in ssh_client.run_command.call_args_list]
    assert any("xray -test" in cmd for cmd in calls)
    ssh_client.run_command.assert_any_call(_SYSTEMD_RESTART_CMD)


@pytest.mark.asyncio
@pytest.mark.usefixtures("_mock_upload")
async def test_deploy_xray_config_rolls_back_on_invalid(ssh_client: SSHClient, mocker):
    # xray -test не вернул "Configuration OK" → невалидный конфиг.
    mocker.patch.object(ssh_client, "run_command", return_value=("error: bad config", ""))

    with pytest.raises(RuntimeError, match="rolled back"):
        await ssh_client.deploy_xray_config("{bad}", xray_runtime="systemd")

    calls = [c.args[0] for c in ssh_client.run_command.call_args_list]
    # Откат выполнен, рестарт НЕ вызван.
    assert any("mv -f" in cmd for cmd in calls)
    assert _SYSTEMD_RESTART_CMD not in calls


@pytest.mark.asyncio
@pytest.mark.usefixtures("_mock_upload", "_mock_run")
async def test_deploy_xray_config_uploads_to_correct_path(ssh_client: SSHClient):
    config = '{"test": true}'

    await ssh_client.deploy_xray_config(config, xray_runtime="systemd")

    ssh_client.upload_file.assert_called_once_with(_CONFIG_PATH, config)


@pytest.mark.asyncio
async def test_run_command_returns_stdout_stderr_on_nonzero_exit(ssh_client: SSHClient, mocker):
    mock_result = mocker.Mock()
    mock_result.stdout = "out"
    mock_result.stderr = "err"
    mock_result.returncode = 1

    mock_conn = mocker.AsyncMock()
    mock_conn.run = mocker.AsyncMock(return_value=mock_result)
    mock_conn.__aenter__ = mocker.AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = mocker.AsyncMock(return_value=False)

    mocker.patch.object(ssh_client, "_connect", return_value=mock_conn)

    stdout, stderr = await ssh_client.run_command("bad-cmd")

    assert stdout == "out"
    assert stderr == "err"
