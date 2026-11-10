"""
Authentication and user management forms for ValuLens.
"""

from django import forms
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

User = get_user_model()


class RegisterForm(forms.ModelForm):
    """
    User registration form.
    Requires email and password confirmation, with optional first/last name.
    """

    email = forms.EmailField(
        label="Email Address",
        widget=forms.EmailInput(
            attrs={
                "class": "form-input",
                "placeholder": "you@example.com",
                "autocomplete": "email",
                "required": True,
            }
        ),
    )
    first_name = forms.CharField(
        label="First Name",
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-input",
                "placeholder": "Jane",
                "autocomplete": "given-name",
            }
        ),
    )
    last_name = forms.CharField(
        label="Last Name",
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-input",
                "placeholder": "Doe",
                "autocomplete": "family-name",
            }
        ),
    )
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(
            attrs={
                "class": "form-input",
                "placeholder": "At least 8 characters",
                "autocomplete": "new-password",
                "required": True,
            }
        ),
        help_text="Must be at least 8 characters and not too common.",
    )
    password_confirm = forms.CharField(
        label="Confirm Password",
        widget=forms.PasswordInput(
            attrs={
                "class": "form-input",
                "placeholder": "Re-enter your password",
                "autocomplete": "new-password",
                "required": True,
            }
        ),
    )

    class Meta:
        model = User
        fields = ("email", "first_name", "last_name")

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account with this email address already exists.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        password_confirm = cleaned_data.get("password_confirm")

        if password and password_confirm:
            if password != password_confirm:
                self.add_error("password_confirm", "Passwords do not match.")
            else:
                # Validate against Django password validators
                temp_user = User(
                    email=cleaned_data.get("email", ""),
                    first_name=cleaned_data.get("first_name", ""),
                    last_name=cleaned_data.get("last_name", ""),
                )
                try:
                    validate_password(password, user=temp_user)
                except ValidationError as error:
                    self.add_error("password", error)

        return cleaned_data

    def save(self, commit=True):
        user = User(
            email=self.cleaned_data["email"],
            first_name=self.cleaned_data.get("first_name", ""),
            last_name=self.cleaned_data.get("last_name", ""),
        )
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user


class LoginForm(forms.Form):
    """
    User login form authenticating with email and password.
    """

    email = forms.EmailField(
        label="Email Address",
        widget=forms.EmailInput(
            attrs={
                "class": "form-input",
                "placeholder": "you@example.com",
                "autocomplete": "email",
                "required": True,
                "autofocus": True,
            }
        ),
    )
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(
            attrs={
                "class": "form-input",
                "placeholder": "••••••••",
                "autocomplete": "current-password",
                "required": True,
            }
        ),
    )

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user_cache = None
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get("email", "").strip().lower()
        password = cleaned_data.get("password")

        if email and password:
            self.user_cache = authenticate(
                self.request,
                username=email,
                password=password,
            )
            if self.user_cache is None:
                raise ValidationError("Invalid email or password. Please try again.")
            if not self.user_cache.is_active:
                raise ValidationError("This account is currently inactive.")

        return cleaned_data

    def get_user(self):
        return self.user_cache


class ProfileUpdateForm(forms.ModelForm):
    """
    Profile update form for changing basic information.
    """

    first_name = forms.CharField(
        label="First Name",
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-input",
                "placeholder": "First Name",
                "autocomplete": "given-name",
            }
        ),
    )
    last_name = forms.CharField(
        label="Last Name",
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-input",
                "placeholder": "Last Name",
                "autocomplete": "family-name",
            }
        ),
    )

    class Meta:
        model = User
        fields = ("first_name", "last_name")
