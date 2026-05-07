from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0009_taskrecord"),
    ]

    operations = [
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS background_task CASCADE;",
            reverse_sql="",
        ),
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS background_task_completedtask CASCADE;",
            reverse_sql="",
        ),
    ]
