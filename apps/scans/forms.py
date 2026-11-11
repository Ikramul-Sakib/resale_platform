"""
Forms for the scan workflow. Image validation itself happens in
apps.recognition.images (via the scan service), not in the form.
"""

from django import forms
from django.conf import settings

from apps.catalog.models import Brand, Category

from .models import IdentifiedItem


class ScanUploadForm(forms.Form):
    image = forms.FileField(
        label="Item photo",
        widget=forms.ClearableFileInput(
            attrs={
                "class": "form-input",
                "accept": ",".join(settings.ALLOWED_IMAGE_TYPES),
                "data-scan-preview-input": "",
            }
        ),
    )


class IdentificationCorrectionForm(forms.ModelForm):
    category = forms.ModelChoiceField(
        queryset=Category.objects.all(), widget=forms.Select(attrs={"class": "form-select"})
    )
    brand = forms.ModelChoiceField(
        queryset=Brand.objects.all(),
        required=False,
        empty_label="Unknown / not listed",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    class Meta:
        model = IdentifiedItem
        fields = ("title", "category", "brand", "model_name", "condition")
        labels = {"model_name": "Model / SKU"}
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-input"}),
            "model_name": forms.TextInput(attrs={"class": "form-input"}),
            "condition": forms.Select(attrs={"class": "form-select"}),
        }
