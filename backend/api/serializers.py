from rest_framework import serializers


class RaceSerializer(serializers.Serializer):
    round = serializers.IntegerField(min_value=1)
    name = serializers.CharField()
    date = serializers.CharField(allow_null=True)
    location = serializers.CharField()
    country = serializers.CharField()


class DriverStandingSerializer(serializers.Serializer):
    position = serializers.IntegerField(min_value=1)
    driver_name = serializers.CharField()
    points = serializers.FloatField(min_value=0)
    wins = serializers.IntegerField(min_value=0)
    constructor = serializers.CharField()


class ConstructorSerializer(serializers.Serializer):
    position = serializers.IntegerField(min_value=1)
    constructor_name = serializers.CharField()
    points = serializers.FloatField(min_value=0)
    wins = serializers.IntegerField(min_value=0)


class QualifyingResultSerializer(serializers.Serializer):
    position = serializers.IntegerField(allow_null=True)
    driver_number = serializers.IntegerField(allow_null=True)
    driver_name = serializers.CharField()
    team = serializers.CharField()
    q1_time = serializers.CharField(allow_null=True)
    q2_time = serializers.CharField(allow_null=True)
    q3_time = serializers.CharField(allow_null=True)


class RaceResultSerializer(serializers.Serializer):
    position = serializers.IntegerField(allow_null=True)
    driver_number = serializers.IntegerField(allow_null=True)
    driver_name = serializers.CharField()
    team = serializers.CharField()
    points = serializers.IntegerField(min_value=0)
    status = serializers.CharField()
    grid_position = serializers.IntegerField(allow_null=True)
    laps = serializers.IntegerField(min_value=0)


class RaceResultsSerializer(serializers.Serializer):
    qualifying = QualifyingResultSerializer(many=True)
    race = RaceResultSerializer(many=True)


class PracticeResultSerializer(serializers.Serializer):
    position = serializers.IntegerField(min_value=1)
    driver_code = serializers.CharField()
    team = serializers.CharField()
    lap_time = serializers.CharField(allow_null=True)
    lap_number = serializers.IntegerField(allow_null=True)
