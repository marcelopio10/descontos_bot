from django.core.management.base import BaseCommand, CommandError

from apps.social_posts.services.composio_publisher import ComposioPublishError, preflight_account


class Command(BaseCommand):
    help = 'Valida a connected account Instagram do Composio sem publicar mídia.'

    def handle(self, *args, **options):
        try:
            profile = preflight_account()
        except ComposioPublishError as exc:
            raise CommandError(f'[{exc.stage}] {exc}') from exc
        self.stdout.write(self.style.SUCCESS(
            f'Preflight OK | username=@{profile.get("username")} | id={profile.get("id")}'
        ))
