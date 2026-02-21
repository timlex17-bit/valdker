from rest_framework import serializers


class OwnerChatRequestSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=5000, allow_blank=False)


class OwnerChatLinkSerializer(serializers.Serializer):
    title = serializers.CharField()
    url = serializers.CharField()


class OwnerChatCardSerializer(serializers.Serializer):
    label = serializers.CharField()
    value = serializers.CharField()


class OwnerChatResponseSerializer(serializers.Serializer):
    reply_text = serializers.CharField()
    cards = OwnerChatCardSerializer(many=True, required=False)
    links = OwnerChatLinkSerializer(many=True, required=False)
    meta = serializers.DictField(required=False)