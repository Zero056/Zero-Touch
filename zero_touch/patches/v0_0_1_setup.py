from zero_touch.install import after_install, before_install, ensure_custom_fields


def execute():
	before_install()
	after_install()
	ensure_custom_fields()
