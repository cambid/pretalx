from django import forms
from django.conf import settings
from django.db.models import Count
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _
from django_scopes.forms import SafeModelChoiceField

from pretalx.cfp.forms.cfp import CfPFormMixin
from pretalx.common.forms.fields import ImageField
from pretalx.common.forms.widgets import MarkdownWidget
from pretalx.common.mixins.forms import PublicContent, RequestRequire
from pretalx.submission.forms.track_select_widget import TrackSelectWidget
from pretalx.submission.models import Question, Submission, SubmissionStates


class InfoForm(CfPFormMixin, RequestRequire, PublicContent, forms.ModelForm):
    additional_speaker = forms.EmailField(
        label=_("Additional Speaker"),
        help_text=_(
            "If you have a co-speaker, please add their email address here, and we will invite them to create an account. If you have more than one co-speaker, you can add more speakers after finishing the proposal process."
        ),
        required=False,
    )
    image = ImageField(
        required=False,
        label=_("Session image"),
        help_text=_("Use this if you want an illustration to go with your proposal."),
    )

    def __init__(self, event, **kwargs):
        self.event = event
        self.readonly = kwargs.pop("readonly", False)
        self.access_code = kwargs.pop("access_code", None)
        instance = kwargs.get("instance")
        initial = kwargs.pop("initial", {}) or {}
        if not instance or not instance.submission_type:
            initial["submission_type"] = (
                getattr(self.access_code, "submission_type", None)
                or initial.get("submission_type")
                or self.event.cfp.default_type
            )
        if not instance and self.access_code:
            initial["track"] = self.access_code.track
        if not instance or not instance.content_locale:
            initial["content_locale"] = self.event.locale

        super().__init__(initial=initial, **kwargs)

        self.fields["title"].label = _("Proposal title")
        if "abstract" in self.fields:
            self.fields["abstract"].widget.attrs["rows"] = 2
        if instance and instance.pk:
            self.fields.pop("additional_speaker")

        self._set_track(instance=instance)
        self._set_submission_types(instance=instance)
        self._set_locales()
        self._set_slot_count(instance=instance)

        if self.readonly:
            for f in self.fields.values():
                f.disabled = True

    def _set_track(self, instance=None):
        if "track" in self.fields:
            if (
                not self.event.settings.use_tracks
                or instance
                and instance.state != SubmissionStates.SUBMITTED
            ):
                self.fields.pop("track")
                return

            access_code = self.access_code or getattr(instance, "access_code", None)
            if not access_code or not access_code.track:
                self.fields["track"].queryset = self.event.tracks.filter(
                    requires_access_code=False
                )
            else:
                self.fields["track"].queryset = self.event.tracks.filter(
                    pk=access_code.track.pk
                )
            if len(self.fields["track"].queryset) == 1:
                self.initial["track"] = self.fields["track"].queryset.first().pk
                self.fields["track"].widget = forms.HiddenInput()

    def _set_submission_types(self, instance=None):
        _now = now()
        if (
            instance
            and instance.pk
            and (
                instance.state != SubmissionStates.SUBMITTED
                or not self.event.cfp.is_open
            )
        ):
            self.fields[
                "submission_type"
            ].queryset = self.event.submission_types.filter(
                pk=instance.submission_type_id
            )
            self.fields["submission_type"].disabled = True
            return
        access_code = self.access_code or getattr(instance, "access_code", None)
        if access_code and not access_code.submission_type:
            pks = set(self.event.submission_types.values_list("pk", flat=True))
        elif access_code:
            pks = {access_code.submission_type.pk}
        else:
            queryset = self.event.submission_types.filter(requires_access_code=False)
            if (
                not self.event.cfp.deadline or self.event.cfp.deadline >= _now
            ):  # No global deadline or still open
                types = queryset.exclude(deadline__lt=_now)
            else:
                types = queryset.filter(deadline__gte=_now)
            pks = set(types.values_list("pk", flat=True))
        if instance and instance.pk:
            pks |= {instance.submission_type.pk}
        self.fields["submission_type"].queryset = self.event.submission_types.filter(
            pk__in=pks
        )
        if len(pks) == 1:
            self.initial["submission_type"] = (
                self.fields["submission_type"].queryset.first().pk
            )
            self.fields["submission_type"].widget = forms.HiddenInput()

    def _set_locales(self):
        if len(self.event.locales) == 1:
            self.initial["content_locale"] = self.event.locales[0]
            self.fields["content_locale"].widget = forms.HiddenInput()
        else:
            locale_names = dict(settings.LANGUAGES)
            self.fields["content_locale"].choices = [
                (a, locale_names[a]) for a in self.event.locales
            ]

    def _set_slot_count(self, instance=None):
        if not self.event.settings.present_multiple_times:
            self.fields.pop("slot_count", None)
        elif (
            "slot_count" in self.fields
            and instance
            and instance.state
            in [SubmissionStates.ACCEPTED, SubmissionStates.CONFIRMED]
        ):
            self.fields["slot_count"].disabled = True
            self.fields["slot_count"].help_text += " " + str(
                _(
                    "Please contact the organisers if you want to change how often you're presenting this proposal."
                )
            )

    class Meta:
        model = Submission
        fields = [
            "title",
            "submission_type",
            "track",
            "content_locale",
            "abstract",
            "description",
            "notes",
            "slot_count",
            "do_not_record",
            "image",
            "duration",
        ]
        request_require = [
            "title",
            "abstract",
            "description",
            "notes",
            "image",
            "do_not_record",
            "track",
            "duration",
        ]
        public_fields = ["title", "abstract", "description", "image"]
        widgets = {
            "abstract": MarkdownWidget,
            "description": MarkdownWidget,
            "notes": MarkdownWidget,
            "track": TrackSelectWidget,
        }
        field_classes = {
            "submission_type": SafeModelChoiceField,
            "track": SafeModelChoiceField,
        }


class SubmissionFilterForm(forms.Form):
    state = forms.MultipleChoiceField(
        choices=SubmissionStates.get_choices(),
        required=False,
        widget=forms.SelectMultiple(attrs={"class": "select2"}),
    )
    submission_type = forms.MultipleChoiceField(
        required=False, widget=forms.SelectMultiple(attrs={"class": "select2"})
    )
    track = forms.MultipleChoiceField(
        required=False, widget=forms.SelectMultiple(attrs={"class": "select2"})
    )
    tags = forms.MultipleChoiceField(
        required=False, widget=forms.SelectMultiple(attrs={"class": "select2"})
    )
    question = SafeModelChoiceField(queryset=Question.objects.none(), required=False)

    def __init__(self, event, *args, **kwargs):
        self.event = event
        usable_states = kwargs.pop("usable_states", None)
        super().__init__(*args, **kwargs)
        qs = event.submissions
        state_qs = Submission.all_objects.filter(event=event)
        if usable_states:
            qs = qs.filter(state__in=usable_states)
            state_qs = state_qs.filter(state__in=usable_states)
        state_count = {
            d["state"]: d["state__count"]
            for d in state_qs.order_by("state").values("state").annotate(Count("state"))
        }
        type_count = {
            d["submission_type_id"]: d["submission_type_id__count"]
            for d in qs.order_by("submission_type_id")
            .values("submission_type_id")
            .annotate(Count("submission_type_id"))
        }
        track_count = {
            d["track"]: d["track__count"]
            for d in qs.order_by("track").values("track").annotate(Count("track"))
        }
        tag_count = event.tags.prefetch_related("submissions").annotate(
            submission_count=Count("submissions", distinct=True)
        )
        tag_count = {tag.tag: tag.submission_count for tag in tag_count}
        self.fields["submission_type"].choices = [
            (sub_type.pk, f"{str(sub_type.name)} ({type_count.get(sub_type.pk, 0)})")
            for sub_type in event.submission_types.all()
        ]
        self.fields["submission_type"].widget.attrs["title"] = _("Session types")
        if usable_states:
            usable_states = [
                choice
                for choice in self.fields["state"].choices
                if choice[0] in usable_states
            ]
        else:
            usable_states = self.fields["state"].choices
        self.fields["state"].choices = [
            (choice[0], f"{choice[1].capitalize()} ({state_count.get(choice[0], 0)})")
            for choice in usable_states
        ]
        self.fields["state"].widget.attrs["title"] = _("Proposal states")
        self.fields["track"].choices = [
            (track.pk, f"{track.name} ({track_count.get(track.pk, 0)})")
            for track in event.tracks.all()
        ]
        self.fields["track"].widget.attrs["title"] = _("Tracks")
        self.fields["question"].queryset = event.questions.all()
        self.fields["tags"].widget.attrs["title"] = _("Tags")
        if not self.event.tags.all().exists():
            self.fields.pop("tags")
        else:
            self.fields["tags"].choices = [
                (tag.pk, f"{tag.tag} ({tag_count.get(tag.tag, 0)})")
                for tag in self.event.tags.all()
            ]
