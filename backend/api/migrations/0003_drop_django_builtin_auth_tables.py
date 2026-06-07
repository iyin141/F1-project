from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0002_sectoraggregate"),
    ]

    operations = [
        migrations.RunSQL(
            sql=migrations.RunSQL.noop,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]