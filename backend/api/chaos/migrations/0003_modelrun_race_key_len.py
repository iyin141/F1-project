from django.db import migrations, models


class Migration(migrations.Migration):
    """ModelRun.race_key held "2024-05" (7 chars) but a backtest saves "loso-2018-2025" (14): Postgres rejected it with
    varchar(12). SQLite does not enforce the length, so the unit tests passed."""

    dependencies = [
        ('chaos', '0002_featureset_modelrun_chaosprediction'),
    ]

    operations = [
        migrations.AlterField(
            model_name='modelrun',
            name='race_key',
            field=models.CharField(blank=True, default='', max_length=32),
        ),
    ]
