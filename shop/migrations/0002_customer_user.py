from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Adds the optional `user` link from Customer to auth.User.

    Keeps the same migration name as the previously-applied migration in
    older databases, so existing databases (where the column already exists
    and the migration is recorded as applied) skip this migration cleanly,
    while fresh databases get the column created here.
    """

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('shop', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='customer',
            name='user',
            field=models.OneToOneField(
                blank=True,
                help_text='Link to a system user account if this customer logs in via the portal',
                null=True,
                on_delete=models.deletion.SET_NULL,
                related_name='customer_profile',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
