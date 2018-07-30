# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
import jsonfield.fields


class Migration(migrations.Migration):

    dependencies = [
        ('npoed_grading_features', '0001_initial'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='coursepassinggradeuserstatus',
            name='fail_status_messages',
        ),
        migrations.AddField(
            model_name='coursepassinggradeuserstatus',
            name='status_messages',
            field=jsonfield.fields.JSONField(default={}, verbose_name=b'Message that specifies what user has to do to pass'),
        ),
    ]
