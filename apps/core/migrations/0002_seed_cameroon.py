from django.db import migrations

from apps.core.seed import load, unload


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]
    operations = [migrations.RunPython(load, unload)]
