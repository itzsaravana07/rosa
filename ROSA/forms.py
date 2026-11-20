from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import Address, Profile

User = get_user_model()


class RegisterForm(UserCreationForm):
    first_name = forms.CharField(max_length=60, label="First name")
    email = forms.EmailField(label="Email address")

    class Meta:
        model = User
        fields = ("username", "first_name", "email", "password1", "password2")

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email


class UserForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "email")


class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ("phone", "picture")


class AddressForm(forms.ModelForm):
    class Meta:
        model = Address
        fields = ("full_name", "phone", "line1", "line2", "city", "state", "pincode", "is_default")

    def clean_pincode(self):
        pin = self.cleaned_data["pincode"].strip()
        if not (pin.isdigit() and len(pin) == 6):
            raise forms.ValidationError("Enter a 6-digit PIN code.")
        return pin
