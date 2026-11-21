import { AuthService } from '../auth/services/auth.service';
import { UserRole } from '../shared/models/user.model';

/** L'évaluation des dégâts à pied : le personnel municipal et les élus (décision du 20/11/2026),
 * l'administrateur pour dépanner — comme `Compte.evalueLesDegats` sur Android. Le serveur
 * vérifie en plus la commune et le module de dégâts. */
export function evalueLesDegats(auth: AuthService): boolean {
  const role = auth.getEffectiveRole();
  return role === UserRole.LOCAL_AUTH || role === UserRole.ADMIN;
}
