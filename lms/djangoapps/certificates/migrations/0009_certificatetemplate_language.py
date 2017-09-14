# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('certificates', '0008_schema__remove_badges'),
    ]

    operations = [
        migrations.AddField(
            model_name='certificatetemplate',
            name='language',
            field=models.CharField(help_text='Only certificates for courses in the selected language will be rendered using this template.<br />*Note* Course language is determined by the first two letters of the language code.', max_length=2, null=True, blank=True),
        ),
    ]
