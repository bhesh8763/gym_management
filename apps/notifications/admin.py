from django.contrib import admin
from .models import Notification, MessageGroup, GroupMessage, PinnedConversation


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('recipient', 'notification_type', 'title', 'is_read', 'created_at')
    list_filter = ('notification_type', 'is_read')
    search_fields = ('recipient__email', 'title')
    readonly_fields = ('created_at',)


class GroupMessageInline(admin.TabularInline):
    model = GroupMessage
    extra = 0
    readonly_fields = ('sender', 'message', 'is_edited', 'created_at')


@admin.register(MessageGroup)
class MessageGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_by', 'member_count', 'created_at')
    search_fields = ('name', 'created_by__email')
    filter_horizontal = ('members',)
    inlines = [GroupMessageInline]

    @admin.display(description='Members')
    def member_count(self, obj):
        return obj.members.count()


@admin.register(GroupMessage)
class GroupMessageAdmin(admin.ModelAdmin):
    list_display = ('group', 'sender', 'message_preview', 'is_edited', 'created_at')
    list_filter = ('is_edited',)
    search_fields = ('sender__email', 'message')
    readonly_fields = ('created_at',)

    @admin.display(description='Message')
    def message_preview(self, obj):
        return obj.message[:60] + ('...' if len(obj.message) > 60 else '')


@admin.register(PinnedConversation)
class PinnedConversationAdmin(admin.ModelAdmin):
    list_display = ('user', 'kind', 'target_id', 'created_at')
    list_filter = ('kind',)
    search_fields = ('user__email',)
