from djongo import models

class Participacion(models.Model):
    tipoRelacion = models.CharField(max_length=255)
    nombreEmpresaSociedadAsociacion = models.CharField(max_length=255)
    porcentajeParticipacion = models.FloatField()

    class Meta:
        abstract = True  # Indicar que es un modelo embebido

class DatosGenerales(models.Model):
    nombre = models.CharField(max_length=255)
    primerApellido = models.CharField(max_length=255)
    segundoApellido = models.CharField(max_length=255)

    class Meta:
        abstract = True  # Indicar que es un modelo embebido

class DatosEmpleoCargoComision(models.Model):
    empleoCargoComision = models.CharField(max_length=255)
    nivelOrdenGobierno = models.CharField(max_length=255)
    nombreEntePublico = models.CharField(max_length=255)
    entidadFederativa = models.CharField(max_length=255)

    class Meta:
        abstract = True  # Indicar que es un modelo embebido

class Declaracion(models.Model):
    situacionPatrimonial = models.EmbeddedField(
        model_container=DatosGenerales
    )
    datosEmpleoCargoComision = models.EmbeddedField(
        model_container=DatosEmpleoCargoComision
    )
    interes = models.ArrayField(
        model_container=Participacion
    )

    class Meta:
        abstract = True  # Indicar que es un modelo embebido

class Sistema1(models.Model):
    declaracion = models.EmbeddedField(
        model_container=Declaracion
    )
    objects = models.DjongoManager()
