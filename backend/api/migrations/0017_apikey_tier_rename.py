# Generated migration for tier naming alignment
# Renames tiers: basic -> standard, pro -> premium, enterprise -> internal

from django.db import migrations, models


def rename_tiers_forward(apps, schema_editor):
    """Migrate old tier names to new ones."""
    APIKey = apps.get_model('api', 'APIKey')
    tier_map = {
        'basic': 'standard',
        'pro': 'premium',
        'enterprise': 'internal',
    }
    for old_tier, new_tier in tier_map.items():
        APIKey.objects.filter(tier=old_tier).update(tier=new_tier)


def rename_tiers_backward(apps, schema_editor):
    """Rollback tier names to old ones."""
    APIKey = apps.get_model('api', 'APIKey')
    tier_map = {
        'standard': 'basic',
        'premium': 'pro',
        'internal': 'enterprise',
    }
    for new_tier, old_tier in tier_map.items():
        APIKey.objects.filter(tier=new_tier).update(tier=old_tier)


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0016_apikey'),
    ]

    operations = [
        migrations.AlterField(
            model_name='apikey',
            name='tier',
            field=models.CharField(
                choices=[
                    ('free', 'Free'),
                    ('standard', 'Standard'),
                    ('premium', 'Premium'),
                    ('internal', 'Internal'),
                ],
                db_index=True,
                default='free',
                max_length=20,
            ),
        ),
        migrations.RunPython(rename_tiers_forward, rename_tiers_backward),
    ]
