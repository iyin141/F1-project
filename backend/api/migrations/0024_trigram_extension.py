from django.db import migrations
from django.contrib.postgres.operations import TrigramExtension

class Migration(migrations.Migration):

    dependencies = [
        ('api', '0023_remove_sessiondata_idx_sd_year_round_and_more'),
    ]

    operations = [
        TrigramExtension(),
    ]
