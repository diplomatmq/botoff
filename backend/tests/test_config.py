from app.config import Settings


def test_admin_password_has_no_insecure_default():
    assert Settings.model_fields["admin_password"].default == ""
